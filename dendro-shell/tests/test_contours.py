from dendro_shell.contours import closed_rings_from_project, contours_to_geojson
from dendro_shell.project import MeasurePath, Point, Project, RingTick


def test_closed_rings_geojson():
    project = Project(
        image_path="x.png",
        sample_type="disc",
        sample_code="D1",
        pith=Point(x=50, y=50),
        paths=[
            MeasurePath(
                points=[Point(x=50, y=50), Point(x=100, y=50)],
                rings=[
                    RingTick(distance_px=20, year=2020),
                    RingTick(distance_px=40, year=2019),
                ],
            )
        ],
    )
    rings = closed_rings_from_project(project, n_angles=12)
    assert len(rings) == 2
    assert rings[0][0].x == rings[0][-1].x
    gj = contours_to_geojson(project)
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 2
